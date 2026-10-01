#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <ImageIO/ImageIO.h>

static void respond(NSDictionary *value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
    fflush(stdout);
}

int main(void) {
    char *line = NULL;
    size_t capacity = 0;
    while (getline(&line, &capacity, stdin) > 0) {
        @autoreleasepool {
            @try {
                NSError *error = nil;
                NSData *bytes = [[NSString stringWithUTF8String:line] dataUsingEncoding:NSUTF8StringEncoding];
                NSDictionary *input = [NSJSONSerialization JSONObjectWithData:bytes options:0 error:&error];
                if (!input || error) { respond(@{@"error": @"Invalid JSON input"}); continue; }
                VNRecognizeTextRequest *request = [[VNRecognizeTextRequest alloc] init];
                request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
                request.usesLanguageCorrection = YES;
                NSArray *languages = [request supportedRecognitionLanguagesAndReturnError:&error];
                if ([input[@"operation"] isEqual:@"languages"]) {
                    respond(@{@"languages": languages ?: @[], @"engine": @"Apple Vision"});
                    continue;
                }
                NSString *language = input[@"language"] ?: @"en-US";
                if (![languages containsObject:language]) {
                    respond(@{@"error": [@"Unsupported OCR language: " stringByAppendingString:language]});
                    continue;
                }
                request.recognitionLanguages = @[language];
                request.minimumTextHeight = 0.018;
                NSData *imageData = input[@"image"] ? [[NSData alloc] initWithBase64EncodedString:input[@"image"] options:0]
                                                   : [NSData dataWithContentsOfFile:input[@"path"]];
                if (!imageData) { respond(@{@"error": @"Image could not be read"}); continue; }
                CGImageSourceRef source = CGImageSourceCreateWithData((__bridge CFDataRef)imageData, NULL);
                CGImageRef image = source ? CGImageSourceCreateImageAtIndex(source, 0, NULL) : NULL;
                if (source) CFRelease(source);
                if (!image) { respond(@{@"error": @"Image could not be decoded"}); continue; }
                VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:image options:@{}];
                BOOL success = [handler performRequests:@[request] error:&error];
                CGImageRelease(image);
                if (!success) { respond(@{@"error": error.localizedDescription ?: @"OCR failed"}); continue; }
                NSArray *observations = [request.results sortedArrayUsingComparator:^NSComparisonResult(VNRecognizedTextObservation *a, VNRecognizedTextObservation *b) {
                    if (fabs(CGRectGetMidY(a.boundingBox) - CGRectGetMidY(b.boundingBox)) > 0.035)
                        return CGRectGetMidY(a.boundingBox) > CGRectGetMidY(b.boundingBox) ? NSOrderedAscending : NSOrderedDescending;
                    return a.boundingBox.origin.x < b.boundingBox.origin.x ? NSOrderedAscending : NSOrderedDescending;
                }];
                NSMutableArray *items = [NSMutableArray array];
                NSMutableArray *texts = [NSMutableArray array];
                for (VNRecognizedTextObservation *observation in observations) {
                    VNRecognizedText *candidate = [observation topCandidates:1].firstObject;
                    if (!candidate) continue;
                    CGRect box = observation.boundingBox;
                    [items addObject:@{@"text": candidate.string, @"confidence": @(candidate.confidence),
                                       @"box": @[@(box.origin.x), @(1 - CGRectGetMaxY(box)), @(box.size.width), @(box.size.height)]}];
                    [texts addObject:candidate.string];
                }
                NSMutableArray *unreadable = [NSMutableArray array];
                if (items.count == 0) {
                    VNDetectTextRectanglesRequest *detector = [[VNDetectTextRectanglesRequest alloc] init];
                    detector.reportCharacterBoxes = YES;
                    [handler performRequests:@[detector] error:nil];
                    for (VNTextObservation *observation in detector.results) {
                        CGRect box = observation.boundingBox;
                        if (observation.characterBoxes.count >= 3 && box.size.width > 0.05 && box.size.height > 0.04) {
                            [unreadable addObject:@[@(box.origin.x), @(1 - CGRectGetMaxY(box)), @(box.size.width), @(box.size.height)]];
                        }
                    }
                }
                respond(@{@"items": items, @"text": [texts componentsJoinedByString:@"\n"], @"unreadable_boxes": unreadable});
            } @catch (NSException *exception) {
                respond(@{@"error": exception.reason ?: @"OCR exception"});
            }
        }
    }
    free(line);
    return 0;
}
